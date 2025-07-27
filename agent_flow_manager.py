import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from gemini_client import gemini_client
from db import db
from business import BusinessResponse
from news_agent import news_agent

logger = logging.getLogger(__name__)

class FlowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

class AgentFlowManager:
    def __init__(self):
        self.active_flows: Dict[int, str] = {}  # user_id -> flow_id
        self.flow_logs: Dict[str, List[Dict]] = {}
        self.flow_results: Dict[str, Dict] = {}
        self.flow_status: Dict[str, FlowStatus] = {}
        self.stop_signals: Dict[str, bool] = {}
        
    async def start_agent_flow(self, user_id: int, source_urls: List[str], business_id: int, business_data: BusinessResponse) -> str:
        """Start a new agent flow for a user with business data"""
        # Check if user already has an active flow
        if user_id in self.active_flows:
            existing_flow_id = self.active_flows[user_id]
            if self.flow_status.get(existing_flow_id) == FlowStatus.RUNNING:
                raise ValueError("User already has an active agent flow running")
        
        # Create new flow
        flow_id = str(uuid.uuid4())
        self.active_flows[user_id] = flow_id
        self.flow_logs[flow_id] = []
        self.flow_status[flow_id] = FlowStatus.PENDING
        self.stop_signals[flow_id] = False
        
        # Save flow to database
        await self._save_flow_to_db(flow_id, user_id, business_id, source_urls, business_data)
        
        # Start the agent flow in background
        asyncio.create_task(self._execute_agent_flow(flow_id, user_id, business_id, source_urls, business_data))
        
        return flow_id
    
    async def stop_agent_flow(self, user_id: int, flow_id: str) -> bool:
        """Stop an active agent flow"""
        if user_id not in self.active_flows or self.active_flows[user_id] != flow_id:
            return False
            
        if flow_id in self.stop_signals:
            self.stop_signals[flow_id] = True
            self.flow_status[flow_id] = FlowStatus.STOPPED
            await self._log_flow_event(flow_id, "SYSTEM", "Flow stopped by user")
            await self._update_flow_status_in_db(flow_id, FlowStatus.STOPPED)
            return True
        return False
    
    def get_flow_logs(self, flow_id: str) -> List[Dict]:
        """Get logs for a specific flow"""
        return self.flow_logs.get(flow_id, [])
    
    def get_flow_result(self, flow_id: str) -> Optional[Dict]:
        """Get result for a completed flow"""
        return self.flow_results.get(flow_id)
    
    def get_flow_status(self, flow_id: str) -> Optional[FlowStatus]:
        """Get status of a flow"""
        return self.flow_status.get(flow_id)
    
    async def _save_flow_to_db(self, flow_id: str, user_id: int, business_id: int, source_urls: List[str], business_data: BusinessResponse):
        """Save flow information to database"""
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_flows (flow_id, user_id, business_id, source_urls, status, total_sources)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    flow_id, user_id, business_id, json.dumps(source_urls), FlowStatus.PENDING.value, len(source_urls)
                )
                logger.info(f"Flow {flow_id} saved to database")
        except Exception as e:
            logger.error(f"Error saving flow to database: {e}")
    
    async def _update_flow_status_in_db(self, flow_id: str, status: FlowStatus):
        """Update flow status in database"""
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_flows 
                    SET status = $1, updated_at = $2 
                    WHERE flow_id = $3
                    """,
                    status.value, datetime.utcnow(), flow_id
                )
        except Exception as e:
            logger.error(f"Error updating flow status in database: {e}")
    
    async def _update_flow_progress_in_db(self, flow_id: str, completed_sources: int, failed_sources: int):
        """Update flow progress in database"""
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_flows 
                    SET completed_sources = $1, failed_sources = $2, updated_at = $3 
                    WHERE flow_id = $4
                    """,
                    completed_sources, failed_sources, datetime.utcnow(), flow_id
                )
        except Exception as e:
            logger.error(f"Error updating flow progress in database: {e}")
    
    async def _save_final_result_to_db(self, flow_id: str, result: Dict):
        """Save final result to database"""
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_flows 
                    SET result = $1, updated_at = $2 
                    WHERE flow_id = $3
                    """,
                    json.dumps(result), datetime.utcnow(), flow_id
                )
                logger.info(f"Final result saved for flow {flow_id}")
        except Exception as e:
            logger.error(f"Error saving final result to database: {e}")
    
    async def _log_flow_event(self, flow_id: str, agent: str, message: str, metadata: Dict = None):
        """Log a flow event both in memory and database"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent,
            "message": message,
            "metadata": metadata or {}
        }
        
        if flow_id not in self.flow_logs:
            self.flow_logs[flow_id] = []
        
        self.flow_logs[flow_id].append(log_entry)
        logger.info(f"Flow {flow_id} - {agent}: {message}")
        
        # Save to database
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO flow_logs (flow_id, agent_type, log_level, message, metadata)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    flow_id, agent, "INFO", message, json.dumps(metadata or {})
                )
        except Exception as e:
            logger.error(f"Error saving flow log to database: {e}")
    
    async def _check_stop_signal(self, flow_id: str) -> bool:
        """Check if flow should be stopped"""
        if self.stop_signals.get(flow_id, False):
            await self._log_flow_event(flow_id, "SYSTEM", "Flow stop signal received")
            return True
        return False
    
    async def _execute_agent_flow(self, flow_id: str, user_id: int, business_id: int, source_urls: List[str], business_data: BusinessResponse):
        """Execute the complete agent flow with enhanced functionality"""
        try:
            self.flow_status[flow_id] = FlowStatus.RUNNING
            await self._update_flow_status_in_db(flow_id, FlowStatus.RUNNING)
            await self._log_flow_event(flow_id, "SYSTEM", f"Starting enhanced agent flow for {len(source_urls)} URLs")
            
            # Phase 1: Business Context Analysis
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "CONTEXT", "Analyzing business context")
            business_context = await self._analyze_business_context(flow_id, business_data)
            
            # Phase 2: News Research (NEW)
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "NEWS", "Starting news research")
            news_research = await news_agent.research_company_news(
                flow_id, business_id, business_data.name, business_data.industry_type
            )
            
            # Phase 3: Enhanced Multi-Source Data Ingestion
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "INGESTOR", "Starting enhanced multi-source data ingestion")
            all_scraped_data = {}
            completed_sources = 0
            failed_sources = 0
            
            for i, url in enumerate(source_urls):
                if await self._check_stop_signal(flow_id):
                    return
                    
                await self._log_flow_event(flow_id, "INGESTOR", f"Scraping source {i+1}/{len(source_urls)}: {url}")
                scraped_data = await self._run_enhanced_ingestor_agent(flow_id, business_id, url)
                
                if scraped_data and scraped_data.get('success'):
                    platform_name = self._detect_platform(url)
                    all_scraped_data[platform_name] = scraped_data
                    completed_sources += 1
                    await self._log_flow_event(flow_id, "INGESTOR", f"Successfully scraped {platform_name}")
                else:
                    failed_sources += 1
                    await self._log_flow_event(flow_id, "INGESTOR", f"Failed to scrape {url}")
                
                # Update progress
                await self._update_flow_progress_in_db(flow_id, completed_sources, failed_sources)
            
            if not all_scraped_data:
                raise Exception("No data could be scraped from any source")
            
            await self._log_flow_event(flow_id, "INGESTOR", f"Data ingestion completed for {len(all_scraped_data)} sources")
            
            # Phase 4: Enhanced Parallel Analyzer Agents
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "SYSTEM", "Starting enhanced parallel analysis phase")
            
            combined_data = {
                "business_context": business_context,
                "scraped_data": all_scraped_data,
                "news_research": news_research.get('data', {}) if news_research.get('success') else {}
            }
            
            analyzer_tasks = [
                self._run_content_classifier(flow_id, combined_data),
                self._run_data_extractor(flow_id, combined_data),
                self._run_red_flags_detector(flow_id, combined_data),
                self._run_news_analyzer(flow_id, combined_data)  # NEW
            ]
            
            analyzer_results = await asyncio.gather(*analyzer_tasks, return_exceptions=True)
            
            # Check for exceptions
            for i, result in enumerate(analyzer_results):
                if isinstance(result, Exception):
                    await self._log_flow_event(flow_id, "ANALYZER", f"Analyzer {i+1} failed: {str(result)}")
                    analyzer_results[i] = {"error": str(result)}
            
            content_classification, data_extraction, red_flags, news_analysis = analyzer_results
            
            # Phase 5: Enhanced Parallel Evaluator Agents
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "SYSTEM", "Starting enhanced parallel evaluation phase")
            
            context_data = {
                **combined_data,
                "content_classification": content_classification,
                "data_extraction": data_extraction,
                "red_flags": red_flags,
                "news_analysis": news_analysis
            }
            
            evaluator_tasks = [
                self._run_accuracy_evaluator(flow_id, context_data),
                self._run_impact_evaluator(flow_id, context_data),
                self._run_language_clarity_evaluator(flow_id, context_data),
                self._run_brand_consistency_evaluator(flow_id, context_data),
                self._run_reputation_evaluator(flow_id, context_data)  # NEW
            ]
            
            evaluator_results = await asyncio.gather(*evaluator_tasks, return_exceptions=True)
            
            # Check for exceptions
            for i, result in enumerate(evaluator_results):
                if isinstance(result, Exception):
                    await self._log_flow_event(flow_id, "EVALUATOR", f"Evaluator {i+1} failed: {str(result)}")
                    evaluator_results[i] = {"error": str(result)}
            
            accuracy_eval, impact_eval, language_eval, brand_eval, reputation_eval = evaluator_results
            
            # Phase 6: Enhanced Scorer Agent
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "SCORER", "Computing enhanced Blynx Score")
            
            evaluation_data = {
                **context_data,
                "accuracy_evaluation": accuracy_eval,
                "impact_evaluation": impact_eval,
                "language_evaluation": language_eval,
                "brand_evaluation": brand_eval,
                "reputation_evaluation": reputation_eval
            }
            
            blynx_score = await self._run_enhanced_scorer_agent(flow_id, evaluation_data)
            
            # Phase 7: Enhanced Feedback Generator
            if await self._check_stop_signal(flow_id):
                return
                
            await self._log_flow_event(flow_id, "FEEDBACK", "Generating comprehensive enhanced feedback")
            
            final_data = {
                **evaluation_data,
                "blynx_score": blynx_score
            }
            
            feedback = await self._run_enhanced_feedback_generator(flow_id, final_data)
            
            # Compile final result
            final_result = {
                "flow_id": flow_id,
                "source_urls": source_urls,
                "business_context": business_context,
                "news_research": news_research.get('data', {}) if news_research.get('success') else {},
                "blynx_score": blynx_score,
                "feedback": feedback,
                "analysis_details": {
                    "content_classification": content_classification,
                    "data_extraction": data_extraction,
                    "red_flags": red_flags,
                    "news_analysis": news_analysis,
                    "accuracy_evaluation": accuracy_eval,
                    "impact_evaluation": impact_eval,
                    "language_evaluation": language_eval,
                    "brand_evaluation": brand_eval,
                    "reputation_evaluation": reputation_eval
                },
                "statistics": {
                    "total_sources": len(source_urls),
                    "completed_sources": completed_sources,
                    "failed_sources": failed_sources,
                    "success_rate": completed_sources / len(source_urls) if source_urls else 0
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            self.flow_results[flow_id] = final_result
            self.flow_status[flow_id] = FlowStatus.COMPLETED
            
            await self._save_final_result_to_db(flow_id, final_result)
            await self._update_flow_status_in_db(flow_id, FlowStatus.COMPLETED)
            await self._log_flow_event(flow_id, "SYSTEM", "Enhanced agent flow completed successfully")
            
        except Exception as e:
            logger.error(f"Agent flow {flow_id} failed: {str(e)}")
            self.flow_status[flow_id] = FlowStatus.FAILED
            await self._update_flow_status_in_db(flow_id, FlowStatus.FAILED)
            await self._log_flow_event(flow_id, "SYSTEM", f"Agent flow failed: {str(e)}")
        finally:
            # Clean up active flow
            if user_id in self.active_flows and self.active_flows[user_id] == flow_id:
                del self.active_flows[user_id]
    
    def _detect_platform(self, url: str) -> str:
        """Detect platform from URL"""
        if 'instagram.com' in url:
            return 'instagram'
        elif 'x.com' in url or 'twitter.com' in url:
            return 'x'
        elif 'linkedin.com' in url:
            return 'linkedin'
        else:
            return 'landing_page'
    
    async def _analyze_business_context(self, flow_id: str, business_data: BusinessResponse) -> Dict:
        """Analyze business context"""
        try:
            await self._log_flow_event(flow_id, "CONTEXT", "Analyzing business profile")
            
            prompt = f"""
            Analyze the following business profile and provide context for content evaluation:

            Business Name: {business_data.name}
            Industry: {business_data.industry_type}
            Customer Type: {business_data.customer_type}
            About Us: {business_data.about_us}
            Website: {business_data.landing_page_url}

            Provide a JSON response with:
            1. business_category: (detailed business category)
            2. target_market: (analysis of target market)
            3. brand_voice_expectations: (expected brand voice/tone)
            4. industry_standards: (relevant industry standards)
            5. competitive_landscape: (general competitive context)
            6. key_success_metrics: (what success looks like for this business)
            7. reputation_factors: (factors that impact reputation in this industry)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "CONTEXT", "Business context analysis completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "CONTEXT", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_enhanced_ingestor_agent(self, flow_id: str, business_id: int, source_url: str) -> Dict:
        """Run the enhanced ingestor agent with fallback"""
        from scraping_tasks import scrape_instagram_enhanced, scrape_x_enhanced, scrape_linkedin_enhanced
        from landing_page_agent import landing_page_agent
        
        try:
            # Determine the platform based on URL
            if 'instagram.com' in source_url:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, scrape_instagram_enhanced, business_id, source_url, flow_id
                )
            elif 'x.com' in source_url or 'twitter.com' in source_url:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, scrape_x_enhanced, business_id, source_url, flow_id
                )
            elif 'linkedin.com' in source_url:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, scrape_linkedin_enhanced, business_id, source_url, flow_id
                )
            else:
                # Treat as landing page
                result = landing_page_agent.scrape_basic(source_url)
            
            return result
        except Exception as e:
            await self._log_flow_event(flow_id, "INGESTOR", f"Error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _run_content_classifier(self, flow_id: str, scraped_data: Dict) -> Dict:
        """Run content classifier agent"""
        try:
            await self._log_flow_event(flow_id, "CLASSIFIER", "Analyzing content type and tone")
            
            prompt = f"""
            Analyze the following content and classify it:

            Content Data: {json.dumps(scraped_data, indent=2)}

            Provide a JSON response with:
            1. content_type: (website, social_media, blog, news, etc.)
            2. tone: (professional, casual, promotional, informative, etc.)
            3. domain: (business, technology, health, education, etc.)
            4. target_audience: (general, professionals, students, etc.)
            5. content_style: (formal, informal, technical, creative, etc.)
            6. confidence_score: (0-100)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "CLASSIFIER", "Content classification completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "CLASSIFIER", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_data_extractor(self, flow_id: str, scraped_data: Dict) -> Dict:
        """Run data extractor agent"""
        try:
            await self._log_flow_event(flow_id, "EXTRACTOR", "Extracting key entities and sections")
            
            prompt = f"""
            Extract key information from the following content:

            Content Data: {json.dumps(scraped_data, indent=2)}

            Provide a JSON response with:
            1. key_entities: [list of important people, organizations, products mentioned]
            2. main_sections: [list of main content sections/topics]
            3. summary: (brief summary of the content)
            4. keywords: [list of important keywords]
            5. call_to_actions: [list of any CTAs found]
            6. contact_info: (any contact information found)
            7. social_links: [social media links found]
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "EXTRACTOR", "Data extraction completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "EXTRACTOR", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_red_flags_detector(self, flow_id: str, scraped_data: Dict) -> Dict:
        """Run red flags detector agent"""
        try:
            await self._log_flow_event(flow_id, "RED_FLAGS", "Detecting potential risks")
            
            prompt = f"""
            Analyze the following content for potential red flags:

            Content Data: {json.dumps(scraped_data, indent=2)}

            Check for and provide a JSON response with:
            1. bias_indicators: [any signs of bias]
            2. misinformation_risk: (low/medium/high) with explanation
            3. toxicity_level: (low/medium/high) with explanation
            4. spam_indicators: [any spam-like characteristics]
            5. misleading_claims: [any potentially misleading statements]
            6. overall_risk_score: (0-100)
            7. recommendations: [suggestions to address any issues]
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "RED_FLAGS", "Red flags detection completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "RED_FLAGS", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_accuracy_evaluator(self, flow_id: str, context_data: Dict) -> Dict:
        """Run accuracy evaluator agent"""
        try:
            await self._log_flow_event(flow_id, "ACCURACY", "Evaluating factual accuracy")
            
            prompt = f"""
            Evaluate the factual accuracy and logical consistency of this content:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. factual_accuracy_score: (0-100)
            2. logical_consistency_score: (0-100)
            3. evidence_quality: (poor/fair/good/excellent)
            4. source_credibility: (low/medium/high)
            5. fact_check_issues: [list of any questionable facts]
            6. logic_gaps: [any logical inconsistencies found]
            7. overall_accuracy_score: (0-100)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "ACCURACY", "Accuracy evaluation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "ACCURACY", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_impact_evaluator(self, flow_id: str, context_data: Dict) -> Dict:
        """Run impact evaluator agent"""
        try:
            await self._log_flow_event(flow_id, "IMPACT", "Evaluating content impact")
            
            prompt = f"""
            Evaluate the impact and value of this content:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. usefulness_score: (0-100)
            2. originality_score: (0-100)
            3. influence_potential: (low/medium/high)
            4. audience_engagement: (poor/fair/good/excellent)
            5. actionability: (low/medium/high)
            6. value_proposition: (description of main value)
            7. overall_impact_score: (0-100)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "IMPACT", "Impact evaluation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "IMPACT", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_language_clarity_evaluator(self, flow_id: str, context_data: Dict) -> Dict:
        """Run language and clarity evaluator agent"""
        try:
            await self._log_flow_event(flow_id, "LANGUAGE", "Evaluating language and clarity")
            
            prompt = f"""
            Evaluate the language quality and clarity of this content:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. readability_score: (0-100)
            2. clarity_score: (0-100)
            3. grammar_quality: (poor/fair/good/excellent)
            4. vocabulary_appropriateness: (poor/fair/good/excellent)
            5. structure_organization: (poor/fair/good/excellent)
            6. communication_effectiveness: (low/medium/high)
            7. overall_language_score: (0-100)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "LANGUAGE", "Language evaluation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "LANGUAGE", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_news_analyzer(self, flow_id: str, context_data: Dict) -> Dict:
        """Run news analyzer agent"""
        try:
            await self._log_flow_event(flow_id, "NEWS_ANALYZER", "Analyzing news research data")
            
            prompt = f"""
            Analyze the news research data in context of the business:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. news_sentiment_score: (0-100, where 100 is most positive)
            2. market_position_analysis: (description of company's market position based on news)
            3. recent_developments: [list of significant recent developments]
            4. public_perception: (positive/neutral/negative with explanation)
            5. competitive_mentions: [any mentions of competitors]
            6. risk_factors: [potential risks identified from news]
            7. opportunities: [opportunities identified from news]
            8. overall_news_impact: (positive/neutral/negative)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "NEWS_ANALYZER", "News analysis completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "NEWS_ANALYZER", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_brand_consistency_evaluator(self, flow_id: str, context_data: Dict) -> Dict:
        """Run brand consistency evaluator agent"""
        try:
            await self._log_flow_event(flow_id, "BRAND", "Evaluating brand consistency")
            
            prompt = f"""
            Evaluate brand consistency across all content and business context:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. visual_consistency_score: (0-100)
            2. message_consistency_score: (0-100)
            3. tone_consistency_score: (0-100)
            4. value_alignment_score: (0-100)
            5. brand_voice_match: (poor/fair/good/excellent)
            6. inconsistencies_found: [list of brand inconsistencies]
            7. brand_strength_indicators: [positive brand elements]
            8. overall_brand_score: (0-100)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "BRAND", "Brand consistency evaluation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "BRAND", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_reputation_evaluator(self, flow_id: str, context_data: Dict) -> Dict:
        """Run reputation evaluator agent"""
        try:
            await self._log_flow_event(flow_id, "REPUTATION", "Evaluating online reputation")
            
            prompt = f"""
            Evaluate online reputation based on all available data:

            Context Data: {json.dumps(context_data, indent=2)}

            Provide a JSON response with:
            1. reputation_score: (0-100)
            2. credibility_indicators: [factors that enhance credibility]
            3. trust_factors: [elements that build trust]
            4. reputation_risks: [potential reputation risks identified]
            5. online_presence_strength: (weak/moderate/strong)
            6. stakeholder_perception: (description of how stakeholders might perceive)
            7. reputation_management_suggestions: [actionable suggestions]
            8. crisis_potential: (low/medium/high with explanation)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "REPUTATION", "Reputation evaluation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "REPUTATION", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_enhanced_scorer_agent(self, flow_id: str, evaluation_data: Dict) -> Dict:
        """Run enhanced scorer agent to compute comprehensive Blynx Score"""
        try:
            await self._log_flow_event(flow_id, "SCORER", "Computing enhanced Blynx Score")
            
            prompt = f"""
            Compute a comprehensive Blynx Score based on all evaluations including news analysis:

            Evaluation Data: {json.dumps(evaluation_data, indent=2)}

            Use enhanced weighted scoring where:
            - Accuracy (25%): Factual correctness and logic
            - Impact (20%): Usefulness and influence
            - Language (15%): Clarity and communication
            - Brand Consistency (15%): Brand alignment and consistency
            - Reputation (15%): Online reputation and trust factors
            - Red Flags (10%): Penalty for risks/issues

            Provide a JSON response with:
            1. accuracy_weighted_score: (0-100)
            2. impact_weighted_score: (0-100)
            3. language_weighted_score: (0-100)
            4. brand_weighted_score: (0-100)
            5. reputation_weighted_score: (0-100)
            6. red_flag_penalty: (0-100)
            7. final_blynx_score: (0-100)
            8. score_breakdown: (detailed explanation of calculation)
            9. grade: (A+, A, A-, B+, B, B-, C+, C, C-, D, F)
            10. performance_category: (Excellent/Good/Average/Below Average/Poor)
            11. news_impact_factor: (how news research affected the score)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "SCORER", "Enhanced Blynx Score computed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "SCORER", f"Error: {str(e)}")
            return {"error": str(e)}
    
    async def _run_enhanced_feedback_generator(self, flow_id: str, final_data: Dict) -> Dict:
        """Run enhanced feedback generator agent"""
        try:
            await self._log_flow_event(flow_id, "FEEDBACK", "Generating comprehensive enhanced feedback")
            
            prompt = f"""
            Generate comprehensive feedback based on all analysis results including news insights:

            Final Data: {json.dumps(final_data, indent=2)}

            Provide a JSON response with:
            1. executive_summary: (high-level overview of findings)
            2. strengths: [list of content and business strengths]
            3. areas_for_improvement: [detailed improvement areas]
            4. critical_issues: [urgent issues requiring immediate attention]
            5. brand_recommendations: [specific brand consistency suggestions]
            6. reputation_recommendations: [reputation management suggestions]
            7. content_strategy_suggestions: [content optimization recommendations]
            8. news_insights: [key insights from news research]
            9. competitive_advantages: [identified competitive strengths]
            10. risk_mitigation: [strategies to address identified risks]
            11. actionable_next_steps: [prioritized action items]
            12. timeline_recommendations: [suggested timeline for improvements]
            13. resource_requirements: [estimated resources needed for improvements]
            14. success_metrics: [KPIs to track improvement progress]
            15. overall_assessment: (comprehensive summary paragraph)
            """
            
            result = await gemini_client.generate_json_content(prompt)
            await self._log_flow_event(flow_id, "FEEDBACK", "Enhanced feedback generation completed")
            return result
            
        except Exception as e:
            await self._log_flow_event(flow_id, "FEEDBACK", f"Error: {str(e)}")
            return {"error": str(e)}

# Global agent flow manager instance
agent_flow_manager = AgentFlowManager()